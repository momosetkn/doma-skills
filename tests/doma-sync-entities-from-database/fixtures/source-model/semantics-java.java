package example.entity;

import com.example.Audited;
import com.example.domain.Money;
import java.io.Serializable;
import java.util.List;
import lombok.Data;
import org.seasar.doma.Association;
import org.seasar.doma.Column;
import org.seasar.doma.Embedded;
import org.seasar.doma.Entity;
import org.seasar.doma.Id;
import org.seasar.doma.Table;
import org.seasar.doma.TenantId;
import org.seasar.doma.Transient;

@Audited(level = @Audited.Level(values = {"a", "b"}))
@Data
@Entity
@Table(catalog = "app", schema = "tenant", name = "orders")
public class Order extends BaseEntity implements Serializable, Comparable<Order> {
    @Id @Column(name = "tenant_id") @TenantId
    String tenantId;

    @Id @Column(name = "order_id")
    Long orderId;

    @Column(name = "amount") @com.example.Valid
    Money amount;

    @Transient
    List<String[]> labels;

    @Association
    Customer customer;

    @Embedded
    Address address;

    String initialized = computeDefault();

    public int score() {
        return orderId == null ? 0 : orderId.intValue();
    }
}
