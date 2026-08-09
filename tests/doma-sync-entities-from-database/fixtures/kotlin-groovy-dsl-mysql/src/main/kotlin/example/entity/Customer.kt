package example.entity

import org.seasar.doma.Column
import org.seasar.doma.Entity
import org.seasar.doma.Id
import org.seasar.doma.Metamodel
import org.seasar.doma.Table

/** Customers */
// HANDWRITTEN-BEGIN:audited-entity-annotations
@Audited
@Entity(metamodel = Metamodel())
// HANDWRITTEN-END:audited-entity-annotations
@Table(catalog = "fixture_catalog", name = "customer")
class Customer {

    /** Customer ID */
    @Id
    @Column(name = "customer_id")
    var customerId: Long = -1L

// HANDWRITTEN-BEGIN:audited-label
    /** Application-owned audited label. */
    fun auditedLabel(): String = "audited-$customerId"
// HANDWRITTEN-END:audited-label
}
