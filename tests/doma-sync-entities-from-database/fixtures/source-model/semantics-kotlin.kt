package example.entity

import com.example.Audited
import com.example.domain.Money
import java.io.Serializable
import org.seasar.doma.Column
import org.seasar.doma.Embedded
import org.seasar.doma.Entity
import org.seasar.doma.Id
import org.seasar.doma.Table
import org.seasar.doma.TenantId
import org.seasar.doma.Transient

@Audited(level = Audited.Level(values = ["a", "b"]))
@Entity
@Table(catalog = "app", schema = "tenant", name = "orders")
class Order(
    @Id @Column(name = "tenant_id") @TenantId val tenantId: String,
    @Id @Column(name = "order_id") val orderId: Long = -1L,
    description: String,
) : BaseEntity(), Serializable {
    @Column(name = "amount")
    @com.example.Valid
    var amount: Money? = null

    @Transient
    var labels: List<String?> = emptyList()

    @Embedded
    var address: Address? = null

    var delegated: String by lazy { "value" }

    var normalized: String = ""
        get() = field.trim()
        set(value) { field = value.trim() }

    init {
        require(description.isNotBlank())
    }

    fun score(): Long {
        return orderId
    }
}
